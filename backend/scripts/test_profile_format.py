"""
Test whether the generated Profile format complies with OASIS requirements
验证: 
1. Twitter Profile生成CSVFormat
2. Reddit Profile生成JSONDetailed format
"""

import os
import sys
import json
import csv
import tempfile

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.oasis_profile_generator import OasisProfileGenerator, OasisAgentProfile


def test_profile_formats():
    """测TestProfileFormat"""
    print("=" * 60)
    print("OASIS ProfileFormat测Test")
    print("=" * 60)
    
    # Create测TestProfile数据
    test_profiles = [
        OasisAgentProfile(
            user_id=0,
            user_name="test_user_123",
            name="Test User",
            bio="A test user for validation",
            persona="Test User is an enthusiastic participant in social discussions.",
            karma=1500,
            friend_count=100,
            follower_count=200,
            statuses_count=500,
            age=25,
            gender="male",
            mbti="INTJ",
            country="China",
            profession="Student",
            interested_topics=["Technology", "Education"],
            source_entity_uuid="test-uuid-123",
            source_entity_type="Student",
        ),
        OasisAgentProfile(
            user_id=1,
            user_name="org_official_456",
            name="Official Organization",
            bio="Official account for Organization",
            persona="This is an official institutional account that communicates official positions.",
            karma=5000,
            friend_count=50,
            follower_count=10000,
            statuses_count=200,
            profession="Organization",
            interested_topics=["Public Policy", "Announcements"],
            source_entity_uuid="test-uuid-456",
            source_entity_type="University",
        ),
    ]
    
    generator = OasisProfileGenerator.__new__(OasisProfileGenerator)
    
    # 使Use临 hour目录
    with tempfile.TemporaryDirectory() as temp_dir:
        twitter_path = os.path.join(temp_dir, "twitter_profiles.csv")
        reddit_path = os.path.join(temp_dir, "reddit_profiles.json")
        
        # 测TestTwitter CSVFormat
        print("\n1. 测TestTwitter Profile (CSVFormat)")
        print("-" * 40)
        generator._save_twitter_csv(test_profiles, twitter_path)
        
        # 读取并验证CSV
        with open(twitter_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            
        print(f"   文件: {twitter_path}")
        print(f"   行数: {len(rows)}")
        print(f"   表头: {list(rows[0].keys())}")
        print(f"\n   Example例数据 (第1行):")
        for key, value in rows[0].items():
            print(f"     {key}: {value}")
        
        # 验证必需字Segment
        required_twitter_fields = ['user_id', 'user_name', 'name', 'bio', 
                                   'friend_count', 'follower_count', 'statuses_count', 'created_at']
        missing = set(required_twitter_fields) - set(rows[0].keys())
        if missing:
            print(f"\n   [错误] 缺少字Segment: {missing}")
        else:
            print(f"\n   [通过] 所has必需字Segment都存在")
        
        # 测TestReddit JSONFormat
        print("\n2. 测TestReddit Profile (JSONDetailed format)")
        print("-" * 40)
        generator._save_reddit_json(test_profiles, reddit_path)
        
        # 读取并验证JSON
        with open(reddit_path, 'r', encoding='utf-8') as f:
            reddit_data = json.load(f)
        
        print(f"   文件: {reddit_path}")
        print(f"    items目数: {len(reddit_data)}")
        print(f"   字Segment: {list(reddit_data[0].keys())}")
        print(f"\n   Example例数据 (第1 items):")
        print(json.dumps(reddit_data[0], ensure_ascii=False, indent=4))
        
        # 验证Detailed format字Segment
        required_reddit_fields = ['realname', 'username', 'bio', 'persona']
        optional_reddit_fields = ['age', 'gender', 'mbti', 'country', 'profession', 'interested_topics']
        
        missing = set(required_reddit_fields) - set(reddit_data[0].keys())
        if missing:
            print(f"\n   [错误] 缺少必需字Segment: {missing}")
        else:
            print(f"\n   [通过] 所has必需字Segment都存在")
        
        present_optional = set(optional_reddit_fields) & set(reddit_data[0].keys())
        print(f"   [信息] 可选字Segment: {present_optional}")
    
    print("\n" + "=" * 60)
    print("测Test完成!")
    print("=" * 60)


def show_expected_formats():
    """Display OASIS expected format"""
    print("\n" + "=" * 60)
    print("OASIS 期望的ProfileFormat参考")
    print("=" * 60)
    
    print("\n1. Twitter Profile (CSVFormat)")
    print("-" * 40)
    twitter_example = """user_id,user_name,name,bio,friend_count,follower_count,statuses_count,created_at
0,user0,User Zero,I am user zero with interests in technology.,100,150,500,2023-01-01
1,user1,User One,Tech enthusiast and coffee lover.,200,250,1000,2023-01-02"""
    print(twitter_example)
    
    print("\n2. Reddit Profile (JSONDetailed format)")
    print("-" * 40)
    reddit_example = [
        {
            "realname": "James Miller",
            "username": "millerhospitality",
            "bio": "Passionate about hospitality & tourism.",
            "persona": "James is a seasoned professional in the Hospitality & Tourism industry...",
            "age": 40,
            "gender": "male",
            "mbti": "ESTJ",
            "country": "UK",
            "profession": "Hospitality & Tourism",
            "interested_topics": ["Economics", "Business"]
        }
    ]
    print(json.dumps(reddit_example, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    test_profile_formats()
    show_expected_formats()


